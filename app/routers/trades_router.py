"""Trades read/close endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.controllers.execution_controller import ExecutionController
from app.controllers.trade_controller import TradeController
from app.dal.audit_log_dal import AuditLogDAL
from app.dal.trade_dal import TradeDAL
from app.engine.risk_engine import RiskEngine
from app.exceptions.domain import TradeNotFoundException
from app.models.api import ApiResponse, TradeLifecycleOut, TradeListOut, TradeOut
from app.models.api.audit import AuditLogOut
from app.routers.deps import (
    get_execution_controller,
    get_risk_engine,
    get_trade_controller,
)

router = APIRouter(prefix="/trades", tags=["trades"])


class CloseRequest(BaseModel):
    exit_price: float


class ReasonRequest(BaseModel):
    reason: str | None = None


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


@router.patch("/{trade_id}/reason", response_model=ApiResponse[TradeOut])
def update_trade_reason(
    trade_id: int,
    req: ReasonRequest,
) -> ApiResponse[TradeOut]:
    """Save or update the free-text reason / strategy note for a trade."""
    t = TradeDAL().update_reason(trade_id, req.reason)
    return ApiResponse[TradeOut].ok(TradeOut.from_row(t))


@router.get("/{trade_id}/lifecycle", response_model=ApiResponse[TradeLifecycleOut])
def get_trade_lifecycle(trade_id: int) -> ApiResponse[TradeLifecycleOut]:
    """Return a trade with its full ordered audit trail."""
    t = TradeDAL().get_by_id(trade_id)
    logs = AuditLogDAL().list_by_trade_id(trade_id)
    payload = TradeLifecycleOut(
        trade=TradeOut.from_row(t),
        audit_trail=[AuditLogOut.from_row(r) for r in logs],
    )
    return ApiResponse[TradeLifecycleOut].ok(payload)


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
