"""Trades read/close endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.controllers.execution_controller import ExecutionController
from app.controllers.trade_controller import TradeController
from app.engine.risk_engine import RiskEngine
from app.exceptions.domain import TradeNotFoundException
from app.models.api import ApiResponse, TradeListOut, TradeOut
from app.routers.deps import (
    get_execution_controller,
    get_risk_engine,
    get_trade_controller,
)

router = APIRouter(prefix="/trades", tags=["trades"])


class CloseRequest(BaseModel):
    """Request body for ``POST /trades/{id}/close``."""

    exit_price: float


@router.get("", response_model=ApiResponse[TradeListOut])
def list_trades(
    limit: int = 50,
    ctrl: TradeController = Depends(get_trade_controller),
) -> ApiResponse[TradeListOut]:
    """List the most recent trades, newest first."""
    rows = ctrl.list(limit=limit)
    payload = TradeListOut(count=len(rows), trades=[TradeOut.from_row(t) for t in rows])
    return ApiResponse[TradeListOut].ok(payload)


@router.get("/{trade_id}", response_model=ApiResponse[TradeOut])
def get_trade(
    trade_id: int,
    ctrl: TradeController = Depends(get_trade_controller),
) -> ApiResponse[TradeOut]:
    """Fetch a single trade by primary key."""
    t = ctrl.get(trade_id)
    return ApiResponse[TradeOut].ok(TradeOut.from_row(t))


@router.post("/{trade_id}/close", response_model=ApiResponse[TradeOut])
def close_trade(
    trade_id: int,
    req: CloseRequest,
    execution: ExecutionController = Depends(get_execution_controller),
    risk: RiskEngine = Depends(get_risk_engine),
) -> ApiResponse[TradeOut]:
    """Close an ``OPEN`` trade at the supplied exit price.

    Also records the realised PnL on the ``RiskEngine`` so the daily-loss
    cap and open-position counter stay consistent.
    """
    t = execution.close_trade(trade_id, req.exit_price)
    if t is None:
        raise TradeNotFoundException(f"trade {trade_id} not found")
    if t.status == "CLOSED" and t.pnl is not None:
        risk.record_trade_close(t.pnl)
    return ApiResponse[TradeOut].ok(TradeOut.from_row(t))
